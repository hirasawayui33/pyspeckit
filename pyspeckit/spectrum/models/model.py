"""
=============================
Generic SpectralModel wrapper 
=============================
.. moduleauthor:: Adam Ginsburg <adam.g.ginsburg@gmail.com>
"""
import numpy as np
from mpfit import mpfit
import copy
import matplotlib.cbook as mpcb
import fitter
from . import mpfit_messages

class SpectralModel(fitter.SimpleFitter):
    """
    A wrapper class for a spectra model.  Includes internal functions to
    generate multi-component models, annotations, integrals, and individual
    components.  The declaration can be complex, since you should name
    individual variables, set limits on them, set the units the fit will be
    performed in, and set the annotations to be used.  Check out some
    of the hyperfine codes (hcn, n2hp) for examples.
    """

    def __init__(self, modelfunc, npars, multisingle='multi', **kwargs):
        """
        modelfunc: the model function to be fitted.  Should take an X-axis (spectroscopic axis)
        as an input, followed by input parameters.
        npars - number of parameters required by the model

        parnames - a list or tuple of the parameter names

        parvalues - the initial guesses for the input parameters (defaults to ZEROS)

        parlimits - the upper/lower limits for each variable     (defaults to ZEROS)

        parfixed  - Can declare any variables to be fixed        (defaults to ZEROS)

        parerror  - technically an output parameter... hmm       (defaults to ZEROS)

        partied   - not the past tense of party.  Can declare, via text, that
            some parameters are tied to each other.  Defaults to zeros like the
            others, but it's not clear if that's a sensible default

        fitunits - convert X-axis to these units before passing to model

        parsteps - minimum step size for each paremeter          (defaults to ZEROS)

        npeaks   - default number of peaks to assume when fitting (can be overridden)

        shortvarnames - TeX names of the variables to use when annotating

        multisingle - Are there multiple peaks (no background will be fit) or
            just a single peak (a background may/will be fit)
        """

        self.modelfunc = modelfunc
        self.npars = npars
        self.multisingle = multisingle
        
        self.parinfo, kwargs = self._make_parinfo(**kwargs)

        self.modelfunc_kwargs = kwargs

    def _make_parinfo(self, params=None, parnames=None, parvalues=None,
            parlimits=None, parlimited=None, parfixed=None, parerror=None,
            partied=None, fitunits=None, parsteps=None, npeaks=1,
            shortvarnames=("A","\\Delta x","\\sigma"), parinfo=None,
            names=None, values=None, limits=None,
            limited=None, fixed=None, error=None, tied=None, steps=None,
            negamp=None,
            limitedmin=None, limitedmax=None,
            minpars=None, maxpars=None,
            **kwargs):

        # for backwards compatibility - partied = tied, etc.
        for varname in str.split("parnames,parvalues,parsteps,parlimits,parlimited,parfixed,parerror,partied",","):
            shortvarname = varname.replace("par","")
            if locals()[shortvarname] is not None:
                # HACK!  locals() failed for unclear reasons...
                exec("%s = %s" % (varname,shortvarname))

        if params is not None and parvalues is not None:
            raise ValueError("parvalues and params both specified; they're redundant so that's not allowed.")
        elif params is not None and parvalues is None:
            parvalues = params

        if parnames is not None: 
            self.parnames = parnames
        elif parnames is None and self.parnames is not None:
            parnames = self.parnames
        if shortvarnames is not None:
            self.shortvarnames = shortvarnames

        if limitedmin is not None:
            if limitedmax is not None:
                parlimits = zip(limitedmin,limitedmax)
            else:
                parlimits = zip(limitedmin,(False,)*len(parnames))
        elif limitedmax is not None:
            parlimits = zip((False,)*len(parnames),limitedmax)

        if minpars is not None:
            if maxpars is not None:
                parlimits = zip(minpars,maxpars)
            else:
                parlimits = zip(minpars,(False,)*len(parnames))
        elif maxpars is not None:
            parlimits = zip((False,)*len(parnames),maxpars)


        self.fitunits = fitunits
        self.npeaks = npeaks

        # this is a clever way to turn the parameter lists into a dict of lists
        # clever = hard to read
        temp_pardict = dict([(varname, np.zeros(self.npars*self.npeaks, dtype='bool'))
            if locals()[varname] is None else (varname, locals()[varname])
            for varname in str.split("parnames,parvalues,parsteps,parlimits,parlimited,parfixed,parerror,partied",",")])
        temp_pardict['parlimits'] = parlimits if parlimits is not None else [(0,0)] * (self.npars*self.npeaks)
        temp_pardict['parlimited'] = parlimited if parlimited is not None else [(False,False)] * (self.npars*self.npeaks)

        # generate the parinfo dict
        # note that 'tied' must be a blank string (i.e. ""), not False, if it is not set
        # parlimited, parfixed, and parlimits are all two-element items (tuples or lists)
        self.parinfo = [ {'n':ii+self.npars*jj,
            'value':temp_pardict['parvalues'][ii+self.npars*jj],
            'step':temp_pardict['parsteps'][ii+self.npars*jj],
            'limits':temp_pardict['parlimits'][ii+self.npars*jj],
            'limited':temp_pardict['parlimited'][ii+self.npars*jj],
            'fixed':temp_pardict['parfixed'][ii+self.npars*jj],
            'parname':temp_pardict['parnames'][ii].upper()+"%0i" % jj,
            'error':temp_pardict['parerror'][ii+self.npars*jj],
            'tied':temp_pardict['partied'][ii+self.npars*jj] if temp_pardict['partied'][ii+self.npars*jj] else ""} 
            for jj in xrange(self.npeaks)
            for ii in xrange(self.npars) ] # order matters!

        # special keyword to specify emission/absorption lines
        if negamp is not None:
            if negamp:
                for p in self.parinfo:
                    if 'AMP' in p['parname']:
                        p['limited'] = (p['limited'][0], True)
                        p['limits']  = (p['limits'][0],  0)
            else:
                for p in self.parinfo:
                    if 'AMP' in p['parname']:
                        p['limited'] = (True, p['limited'][1])
                        p['limits']  = (0, p['limits'][1])   

        return self.parinfo, kwargs


    def n_modelfunc(self, pars, **kwargs):
        """
        Simple wrapper to deal with N independent peaks for a given spectral model
        """
        def L(x):
            v = np.zeros(len(x))
            # use len(pars) instead of self.npeaks because we want this to work
            # independent of the current best fit
            for jj in xrange(len(pars)/self.npars):
                v += self.modelfunc(x, *pars[jj*self.npars:(jj+1)*self.npars], **kwargs)
            return v
        return L

    def mpfitfun(self,x,y,err=None):
        """
        Wrapper function to compute the fit residuals in an mpfit-friendly format
        """
        if err is None:
            def f(p,fjac=None): return [0,(y-self.n_modelfunc(p, **self.modelfunc_kwargs)(x))]
        else:
            def f(p,fjac=None): return [0,(y-self.n_modelfunc(p, **self.modelfunc_kwargs)(x))/err]
        return f

    def __call__(self, *args, **kwargs):
        if self.multisingle == 'single':
            # I can only admit to myself that this is too many layers of abstraction....
            # oh well.
            # Generate a variable-height version of the model
            func = fitter.vheightmodel(self.modelfunc)
            # Pass that into the four-parameter fitter 
            # this REALLY needs to be replaced with an "npar+1" model fitter
            return self._fourparfitter(func)(*args,**kwargs)
        elif self.multisingle == 'multi':
            return self.fitter(*args,**kwargs)


    def fitter(self, xax, data, err=None, quiet=True, veryverbose=False,
            debug=False, parinfo=None, **kwargs):
        """
        Run the fitter.  Must pass the x-axis and data.  Can include
        error, parameter guesses, and a number of verbosity parameters.

        quiet - pass to mpfit.  If False, will print out the parameter values
            for each iteration of the fitter

        veryverbose - print out a variety of mpfit output parameters

        debug - raise an exception (rather than a warning) if chi^2 is nan

        accepts *tied*, *limits*, *limited*, and *fixed* as keyword arguments.
            They must be lists of length len(params)

        parinfo - You can override the class parinfo dict with this, though
            that largely defeats the point of having the wrapper class.  This class
            does NO checking for whether the parinfo dict is valid.

        kwargs are passed to mpfit after going through _make_parinfo to strip out things
        used by this class
        """

        if parinfo is None:
            parinfo, kwargs = self._make_parinfo(**kwargs)
        else:
            if debug: print "Using user-specified parinfo dict"
            # clean out disallowed kwargs (don't want to pass them to mpfit)
            throwaway, kwargs = self._make_parinfo(**kwargs)

        self.xax = xax # the 'stored' xax is just a link to the original
        if hasattr(xax,'convert_to_unit') and self.fitunits is not None:
            # some models will depend on the input units.  For these, pass in an X-axis in those units
            # (gaussian, voigt, lorentz profiles should not depend on units.  Ammonia, formaldehyde,
            # H-alpha, etc. should)
            xax = copy.copy(xax)
            xax.convert_to_unit(self.fitunits, quiet=quiet)

        if np.any(np.isnan(data)) or np.any(np.isinf(data)):
            err[np.isnan(data) + np.isinf(data)] = np.inf
            data[np.isnan(data) + np.isinf(data)] = 0

        if debug:
            for p in parinfo: print p
            print "\n".join(["%s %i: %s" % (p['parname'],p['n'],p['tied']) for p in parinfo])

        mp = mpfit(self.mpfitfun(xax,data,err),parinfo=parinfo,quiet=quiet,**kwargs)
        mpp = mp.params
        if mp.perror is not None: mpperr = mp.perror
        else: mpperr = mpp*0
        chi2 = mp.fnorm

        if mp.status == 0:
            raise Exception(mp.errmsg)

        if veryverbose:
            print "Fit status: ",mp.status
            print "Fit error message: ",mp.errmsg
            print "Fit message: ",mpfit_messages[mp.status]
            for i,p in enumerate(mpp):
                self.parinfo[i]['value'] = p
                print self.parinfo[i]['parname'],p," +/- ",mpperr[i]
            print "Chi2: ",mp.fnorm," Reduced Chi2: ",mp.fnorm/len(data)," DOF:",len(data)-len(mpp)

        self.mp = mp
        self.mpp = mpp#[1:]
        self.mpperr = mpperr#[1:]
        self.model = self.n_modelfunc(mpp,**self.modelfunc_kwargs)(xax)
        if np.isnan(chi2):
            if debug:
                raise ValueError("Error: chi^2 is nan")
            else:
                print "Warning: chi^2 is nan"
        return mpp,self.model,mpperr,chi2

    def slope(self, xinp):
        """
        Find the local slope of the model at location x
        (x must be in xax's units)
        """
        if hasattr(self, 'model'):
            dm = np.diff(self.model)
            # convert requested x to pixels
            xpix = self.xax.x_to_pix(xinp)
            dmx = np.average(dm[xpix-1:xpix+1])
            if np.isfinite(dmx):
                return dmx
            else:
                return 0

    def annotations(self, shortvarnames=None):
        """
        Return a list of TeX-formatted labels
        """
        from decimal import Decimal # for formatting
        svn = self.shortvarnames if shortvarnames is None else shortvarnames
        # if pars need to be replicated....
        if len(svn) < self.npeaks*self.npars:
            svn = svn * self.npeaks
        label_list = [(
                "$%s(%i)$=%8s $\\pm$ %8s" % (svn[ii+jj*self.npars],jj,
                Decimal("%g" % self.mpp[ii+jj*self.npars]).quantize(Decimal("%0.2g" % (min(self.mpp[ii+jj*self.npars],self.mpperr[ii+jj*self.npars])))),
                Decimal("%g" % self.mpperr[ii+jj*self.npars]).quantize(Decimal("%0.2g" % (self.mpperr[ii+jj*self.npars]))),)
                          ) for jj in range(self.npeaks) for ii in range(self.npars)]
        labels = tuple(mpcb.flatten(label_list))
        return labels

    def components(self, xarr, pars):
        """
        Return a numpy ndarray of the independent components of the fits
        """

        modelcomponents = np.array(
            [self.modelfunc(xarr,
                *pars[i*self.npars:(i+1)*self.npars],
                return_components=True,
                **self.modelfunc_kwargs)
            for i in range(self.npeaks)])

        return modelcomponents

    def integral(self, modelpars, **kwargs):
        """
        Extremely simple integrator:
        IGNORES modelpars;
        just sums self.model
        """

        return self.model.sum()
