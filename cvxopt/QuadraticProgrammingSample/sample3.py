#! /usr/bin/python
# -*- coding: utf-8 -*-
u"""
Simple sample code to solve quadratic programming with cvxopt

author Atsushi Sakai
"""
import numpy as np
import math


STEP = 0.99
EXPON = 3
MAXITERS = 100
ABSTOL = 1e-7
RELTOL = 1e-6
FEASTOL = 1e-7
show_progress = True


def kkt_chol2(G, dims, A, mnl=0):
    """
    Solution of KKT equations by reduction to a 2 x 2 system, a sparse
    or dense Cholesky factorization of order n to eliminate the 1,1
    block, and a sparse or dense Cholesky factorization of order p.
    Implemented only for problems with no second-order or semidefinite
    cone constraints.

    Returns a function that (1) computes Cholesky factorizations of
    the matrices

        S = H + GG' * W^{-1} * W^{-T} * GG,
        K = A * S^{-1} *A'

    or (if K is singular in the first call to the function), the matrices

        S = H + GG' * W^{-1} * W^{-T} * GG + A' * A,
        K = A * S^{-1} * A',

    given H, Df, W, where GG = [Df; G], and (2) returns a function for
    solving

        [ H     A'   GG'   ]   [ ux ]   [ bx ]
        [ A     0    0     ] * [ uy ] = [ by ].
        [ GG    0   -W'*W  ]   [ uz ]   [ bz ]

    H is n x n,  A is p x n, Df is mnl x n, G is dims['l'] x n.
    """
    from cvxopt import base, blas, lapack, cholmod
    from cvxopt.base import matrix, spmatrix

    if dims['q'] or dims['s']:
        raise ValueError("kktsolver option 'kkt_chol2' is implemented "
                         "only for problems with no second-order or semidefinite cone "
                         "constraints")
    p, n = A.size
    ml = dims['l']
    F = {'firstcall': True, 'singular': False}

    def factor(W, H=None, Df=None):

        if F['firstcall']:
            if type(G) is matrix:
                F['Gs'] = matrix(0.0, G.size)
            else:
                F['Gs'] = spmatrix(0.0, G.I, G.J, G.size)
            if mnl:
                if type(Df) is matrix:
                    F['Dfs'] = matrix(0.0, Df.size)
                else:
                    F['Dfs'] = spmatrix(0.0, Df.I, Df.J, Df.size)
            if (mnl and type(Df) is matrix) or type(G) is matrix or \
                    type(H) is matrix:
                F['S'] = matrix(0.0, (n, n))
                F['K'] = matrix(0.0, (p, p))
            else:
                F['S'] = spmatrix([], [], [], (n, n), 'd')
                F['Sf'] = None
                if type(A) is matrix:
                    F['K'] = matrix(0.0, (p, p))
                else:
                    F['K'] = spmatrix([], [], [], (p, p), 'd')

        # Dfs = Wnl^{-1} * Df
        if mnl:
            base.gemm(spmatrix(W['dnli'], list(range(mnl)),
                               list(range(mnl))), Df, F['Dfs'], partial=True)

        # Gs = Wl^{-1} * G.
        base.gemm(spmatrix(W['di'], list(range(ml)), list(range(ml))),
                  G, F['Gs'], partial=True)

        if F['firstcall']:
            base.syrk(F['Gs'], F['S'], trans='T')
            if mnl:
                base.syrk(F['Dfs'], F['S'], trans='T', beta=1.0)
            if H is not None:
                F['S'] += H
            try:
                if type(F['S']) is matrix:
                    lapack.potrf(F['S'])
                else:
                    F['Sf'] = cholmod.symbolic(F['S'])
                    cholmod.numeric(F['S'], F['Sf'])
            except ArithmeticError:
                F['singular'] = True
                if type(A) is matrix and type(F['S']) is spmatrix:
                    F['S'] = matrix(0.0, (n, n))
                base.syrk(F['Gs'], F['S'], trans='T')
                if mnl:
                    base.syrk(F['Dfs'], F['S'], trans='T', beta=1.0)
                base.syrk(A, F['S'], trans='T', beta=1.0)
                if H is not None:
                    F['S'] += H
                if type(F['S']) is matrix:
                    lapack.potrf(F['S'])
                else:
                    F['Sf'] = cholmod.symbolic(F['S'])
                    cholmod.numeric(F['S'], F['Sf'])
            F['firstcall'] = False

        else:
            base.syrk(F['Gs'], F['S'], trans='T', partial=True)
            if mnl:
                base.syrk(F['Dfs'], F['S'], trans='T', beta=1.0,
                          partial=True)
            if H is not None:
                F['S'] += H
            if F['singular']:
                base.syrk(A, F['S'], trans='T', beta=1.0, partial=True)
            if type(F['S']) is matrix:
                lapack.potrf(F['S'])
            else:
                cholmod.numeric(F['S'], F['Sf'])

        if type(F['S']) is matrix:
            # Asct := L^{-1}*A'.  Factor K = Asct'*Asct.
            if type(A) is matrix:
                Asct = A.T
            else:
                Asct = matrix(A.T)
            blas.trsm(F['S'], Asct)
            blas.syrk(Asct, F['K'], trans='T')
            lapack.potrf(F['K'])

        else:
            # Asct := L^{-1}*P*A'.  Factor K = Asct'*Asct.
            if type(A) is matrix:
                Asct = A.T
                cholmod.solve(F['Sf'], Asct, sys=7)
                cholmod.solve(F['Sf'], Asct, sys=4)
                blas.syrk(Asct, F['K'], trans='T')
                lapack.potrf(F['K'])
            else:
                Asct = cholmod.spsolve(F['Sf'], A.T, sys=7)
                Asct = cholmod.spsolve(F['Sf'], Asct, sys=4)
                base.syrk(Asct, F['K'], trans='T')
                Kf = cholmod.symbolic(F['K'])
                cholmod.numeric(F['K'], Kf)

        def solve(x, y, z):

            # Solve
            #
            #     [ H          A'  GG'*W^{-1} ]   [ ux   ]   [ bx        ]
            #     [ A          0   0          ] * [ uy   ] = [ by        ]
            #     [ W^{-T}*GG  0   -I         ]   [ W*uz ]   [ W^{-T}*bz ]
            #
            # and return ux, uy, W*uz.
            #
            # If not F['singular']:
            #
            #     K*uy = A * S^{-1} * ( bx + GG'*W^{-1}*W^{-T}*bz ) - by
            #     S*ux = bx + GG'*W^{-1}*W^{-T}*bz - A'*uy
            #     W*uz = W^{-T} * ( GG*ux - bz ).
            #
            # If F['singular']:
            #
            #     K*uy = A * S^{-1} * ( bx + GG'*W^{-1}*W^{-T}*bz + A'*by )
            #            - by
            #     S*ux = bx + GG'*W^{-1}*W^{-T}*bz + A'*by - A'*y.
            #     W*uz = W^{-T} * ( GG*ux - bz ).

            # z := W^{-1} * z = W^{-1} * bz
            scale(z, W, trans='T', inverse='I')

            # If not F['singular']:
            #     x := L^{-1} * P * (x + GGs'*z)
            #        = L^{-1} * P * (x + GG'*W^{-1}*W^{-T}*bz)
            #
            # If F['singular']:
            #     x := L^{-1} * P * (x + GGs'*z + A'*y))
            #        = L^{-1} * P * (x + GG'*W^{-1}*W^{-T}*bz + A'*y)

            if mnl:
                base.gemv(F['Dfs'], z, x, trans='T', beta=1.0)
            base.gemv(F['Gs'], z, x, offsetx=mnl, trans='T',
                      beta=1.0)
            if F['singular']:
                base.gemv(A, y, x, trans='T', beta=1.0)
            if type(F['S']) is matrix:
                blas.trsv(F['S'], x)
            else:
                cholmod.solve(F['Sf'], x, sys=7)
                cholmod.solve(F['Sf'], x, sys=4)

            # y := K^{-1} * (Asc*x - y)
            #    = K^{-1} * (A * S^{-1} * (bx + GG'*W^{-1}*W^{-T}*bz) - by)
            #      (if not F['singular'])
            #    = K^{-1} * (A * S^{-1} * (bx + GG'*W^{-1}*W^{-T}*bz +
            #      A'*by) - by)
            #      (if F['singular']).

            base.gemv(Asct, x, y, trans='T', beta=-1.0)
            if type(F['K']) is matrix:
                lapack.potrs(F['K'], y)
            else:
                cholmod.solve(Kf, y)

            # x := P' * L^{-T} * (x - Asc'*y)
            #    = S^{-1} * (bx + GG'*W^{-1}*W^{-T}*bz - A'*y)
            #      (if not F['singular'])
            #    = S^{-1} * (bx + GG'*W^{-1}*W^{-T}*bz + A'*by - A'*y)
            #      (if F['singular'])

            base.gemv(Asct, y, x, alpha=-1.0, beta=1.0)
            if type(F['S']) is matrix:
                blas.trsv(F['S'], x, trans='T')
            else:
                cholmod.solve(F['Sf'], x, sys=5)
                cholmod.solve(F['Sf'], x, sys=8)

            # W*z := GGs*x - z = W^{-T} * (GG*x - bz)
            if mnl:
                base.gemv(F['Dfs'], x, z, beta=-1.0)
            base.gemv(F['Gs'], x, z, beta=-1.0, offsety=mnl)

        return solve

    return factor


def scale(x, W, trans='N', inverse='N'):
    """
    Applies Nesterov-Todd scaling or its inverse.

    Computes

         x := W*x        (trans is 'N', inverse = 'N')
         x := W^T*x      (trans is 'T', inverse = 'N')
         x := W^{-1}*x   (trans is 'N', inverse = 'I')
         x := W^{-T}*x   (trans is 'T', inverse = 'I').

    x is a dense 'd' matrix.

    W is a dictionary with entries:

    - W['dnl']: positive vector
    - W['dnli']: componentwise inverse of W['dnl']
    - W['d']: positive vector
    - W['di']: componentwise inverse of W['d']
    - W['v']: lists of 2nd order cone vectors with unit hyperbolic norms
    - W['beta']: list of positive numbers
    - W['r']: list of square matrices
    - W['rti']: list of square matrices.  rti[k] is the inverse transpose
      of r[k].

    The 'dnl' and 'dnli' entries are optional, and only present when the
    function is called from the nonlinear solver.
    """
    from cvxopt import blas

    ind = 0

    # Scaling for nonlinear component xk is xk := dnl .* xk; inverse
    # scaling is xk ./ dnl = dnli .* xk, where dnl = W['dnl'],
    # dnli = W['dnli'].

    if 'dnl' in W:
        if inverse == 'N':
            w = W['dnl']
        else:
            w = W['dnli']
        for k in range(x.size[1]):
            blas.tbmv(w, x, n=w.size[0], k=0, ldA=1, offsetx=k * x.size[0])
        ind += w.size[0]

    # Scaling for linear 'l' component xk is xk := d .* xk; inverse
    # scaling is xk ./ d = di .* xk, where d = W['d'], di = W['di'].

    if inverse == 'N':
        w = W['d']
    else:
        w = W['di']
    for k in range(x.size[1]):
        blas.tbmv(w, x, n=w.size[0], k=0, ldA=1, offsetx=k * x.size[0] + ind)
    ind += w.size[0]

    # Scaling for 'q' component is
    #
    #     xk := beta * (2*v*v' - J) * xk
    #         = beta * (2*v*(xk'*v)' - J*xk)
    #
    # where beta = W['beta'][k], v = W['v'][k], J = [1, 0; 0, -I].
    #
    # Inverse scaling is
    #
    #     xk := 1/beta * (2*J*v*v'*J - J) * xk
    #         = 1/beta * (-J) * (2*v*((-J*xk)'*v)' + xk).

    w = matrix(0.0, (x.size[1], 1))
    for k in range(len(W['v'])):
        v = W['v'][k]
        m = v.size[0]
        if inverse == 'I':
            blas.scal(-1.0, x, offset=ind, inc=x.size[0])
        blas.gemv(x, v, w, trans='T', m=m, n=x.size[1], offsetA=ind, ldA=x.size[0])
        blas.scal(-1.0, x, offset=ind, inc=x.size[0])
        blas.ger(v, w, x, alpha=2.0, m=m, n=x.size[1], ldA=x.size[0], offsetA=ind)
        if inverse == 'I':
            blas.scal(-1.0, x, offset=ind, inc=x.size[0])
            a = 1.0 / W['beta'][k]
        else:
            a = W['beta'][k]
        for i in range(x.size[1]):
            blas.scal(a, x, n=m, offset=ind + i * x.size[0])
        ind += m

    # Scaling for 's' component xk is
    #
    #     xk := vec( r' * mat(xk) * r )  if trans = 'N'
    #     xk := vec( r * mat(xk) * r' )  if trans = 'T'.
    #
    # r is kth element of W['r'].
    #
    # Inverse scaling is
    #
    #     xk := vec( rti * mat(xk) * rti' )  if trans = 'N'
    #     xk := vec( rti' * mat(xk) * rti )  if trans = 'T'.
    #
    # rti is kth element of W['rti'].

    maxn = max([0] + [r.size[0] for r in W['r']])
    a = matrix(0.0, (maxn, maxn))
    for k in range(len(W['r'])):

        if inverse == 'N':
            r = W['r'][k]
            if trans == 'N':
                t = 'T'
            else:
                t = 'N'
        else:
            r = W['rti'][k]
            t = trans

        n = r.size[0]
        for i in range(x.size[1]):

            # scale diagonal of xk by 0.5
            blas.scal(0.5, x, offset=ind + i * x.size[0], inc=n + 1, n=n)

            # a = r*tril(x) (t is 'N') or a = tril(x)*r  (t is 'T')
            blas.copy(r, a)
            if t == 'N':
                blas.trmm(x, a, side='R', m=n, n=n, ldA=n, ldB=n,
                          offsetA=ind + i * x.size[0])
            else:
                blas.trmm(x, a, side='L', m=n, n=n, ldA=n, ldB=n,
                          offsetA=ind + i * x.size[0])

            # x := (r*a' + a*r')  if t is 'N'
            # x := (r'*a + a'*r)  if t is 'T'
            blas.syr2k(r, a, x, trans=t, n=n, k=n, ldB=n, ldC=n,
                       offsetC=ind + i * x.size[0])

        ind += n ** 2


def solve_only_equalities_qp(kktsolver, fP, fA, resx0, resy0, dims):
    # Solve
    #
    #     [ P  A' ] [ x ]   [ -q ]
    #     [       ] [   ] = [    ].
    #     [ A  0  ] [ y ]   [  b ]

    #  print(G)
    #  factor = kkt_chol2(G, dims, A)
    #  W = {'d': matrix(0.0, (0, 1)), 'di': matrix(0.0, (0, 1)), 'beta': [], 'v': [], 'r': [], 'rti': []}
    #  print(P)
    #  solver = factor(W, P)

    try:
        f3 = kktsolver({'d': matrix(0.0, (0, 1)), 'di':
                        matrix(0.0, (0, 1)), 'beta': [], 'v': [], 'r': [], 'rti': []})

        #  factor = kkt_chol2(G, dims, A)
        #  W = {'d': matrix(0.0, (0, 1)), 'di': matrix(0.0, (0, 1)), 'beta': [], 'v': [], 'r': [], 'rti': []}
        #  f3 = factor(W, P)

    except ArithmeticError:
        raise ValueError("Rank(A) < p or Rank([P; A; G]) < n")

    x = -1.0 * matrix(q)
    y = matrix(b)
    f3(x, y, matrix(0.0, (0, 1)))
    #  solver(x, y, matrix(0.0, (0, 1)))
    return {'status': 'optimal', 'x': x, 'y': y}


def qp(P, q, G=None, h=None, A=None, b=None):
    """
    Solves a pair of primal and dual convex quadratic cone programs
        minimize    (1/2)*x'*P*x + q'*x
        subject to  G*x + s = h
                    A*x = b
                    s >= 0
        maximize    -(1/2)*(q + G'*z + A'*y)' * pinv(P) * (q + G'*z + A'*y)
                    - h'*z - b'*y
        subject to  q + G'*z + A'*y in range(P)
                    z >= 0.
    The inequalities are with respect to a cone C defined as the Cartesian
    product of N + M + 1 cones:

        C = C_0 x C_1 x .... x C_N x C_{N+1} x ... x C_{N+M}.
    The first cone C_0 is the nonnegative orthant of dimension ml.
    The next N cones are 2nd order cones of dimension mq[0], ..., mq[N-1].
    The second order cone of dimension m is defined as

        { (u0, u1) in R x R^{m-1} | u0 >= ||u1||_2 }.
    The next M cones are positive semidefinite cones of order ms[0], ...,
    ms[M-1] >= 0.
    Input arguments (basic usage).
        P is a dense or sparse 'd' matrix of size (n,n) with the lower
        triangular part of the Hessian of the objective stored in the
        lower triangle.  Must be positive semidefinite.
        q is a dense 'd' matrix of size (n,1).
        dims is a dictionary with the dimensions of the components of C.
        It has three fields.
        - dims['l'] = ml, the dimension of the nonnegative orthant C_0.
          (ml >= 0.)
        - dims['q'] = mq = [ mq[0], mq[1], ..., mq[N-1] ], a list of N
          integers with the dimensions of the second order cones
          C_1, ..., C_N.  (N >= 0 and mq[k] >= 1.)
        - dims['s'] = ms = [ ms[0], ms[1], ..., ms[M-1] ], a list of M
          integers with the orders of the semidefinite cones
          C_{N+1}, ..., C_{N+M}.  (M >= 0 and ms[k] >= 0.)
        The default value of dims = {'l': G.size[0], 'q': [], 's': []}.
        G is a dense or sparse 'd' matrix of size (K,n), where
            K = ml + mq[0] + ... + mq[N-1] + ms[0]**2 + ... + ms[M-1]**2.
        Each column of G describes a vector
            v = ( v_0, v_1, ..., v_N, vec(v_{N+1}), ..., vec(v_{N+M}) )
        in V = R^ml x R^mq[0] x ... x R^mq[N-1] x S^ms[0] x ... x S^ms[M-1]
        stored as a column vector
            [ v_0; v_1; ...; v_N; vec(v_{N+1}); ...; vec(v_{N+M}) ].
        Here, if u is a symmetric matrix of order m, then vec(u) is the
        matrix u stored in column major order as a vector of length m**2.
        We use BLAS unpacked 'L' storage, i.e., the entries in vec(u)
        corresponding to the strictly upper triangular entries of u are
        not referenced.
        h is a dense 'd' matrix of size (K,1), representing a vector in V,
        in the same format as the columns of G.

        A is a dense or sparse 'd' matrix of size (p,n).   The default
        value is a sparse 'd' matrix of size (0,n).
        b is a dense 'd' matrix of size (p,1).  The default value is a
        dense 'd' matrix of size (0,1).
        It is assumed that rank(A) = p and rank([P; A; G]) = n.
        The other arguments are normally not needed.  They make it possible
        to exploit certain types of structure, as described below.
    Output arguments.
        Returns a dictionary with keys 'status', 'x', 's', 'z', 'y',
        'primal objective', 'dual objective', 'gap', 'relative gap',
        'primal infeasibility', 'dual infeasibility', 'primal slack',
        'dual slack', 'iterations'.
        The 'status' field has values 'optimal' or 'unknown'.  'iterations'
        is the number of iterations taken.
        If the status is 'optimal', 'x', 's', 'y', 'z' are an approximate
        solution of the primal and dual optimality conditions
              G*x + s = h,  A*x = b
              P*x + G'*z + A'*y + q = 0
              s >= 0,  z >= 0
              s'*z = 0.
        If the status is 'unknown', 'x', 'y', 's', 'z' are the last
        iterates before termination.  These satisfy s > 0 and z > 0,
        but are not necessarily feasible.
        The values of the other fields are defined as follows.
        - 'primal objective': the primal objective (1/2)*x'*P*x + q'*x.
        - 'dual objective': the dual objective
              L(x,y,z) = (1/2)*x'*P*x + q'*x + z'*(G*x - h) + y'*(A*x-b).
        - 'gap': the duality gap s'*z.
        - 'relative gap': the relative gap, defined as
              gap / -primal objective
          if the primal objective is negative,
              gap / dual objective
          if the dual objective is positive, and None otherwise.
        - 'primal infeasibility': the residual in the primal constraints,
          defined as the maximum of the residual in the inequalities
              || G*x + s + h || / max(1, ||h||)
          and the residual in the equalities
              || A*x - b || / max(1, ||b||).
        - 'dual infeasibility': the residual in the dual constraints,
          defined as
              || P*x + G'*z + A'*y + q || / max(1, ||q||).
        - 'primal slack': the smallest primal slack, sup {t | s >= t*e },
           where
              e = ( e_0, e_1, ..., e_N, e_{N+1}, ..., e_{M+N} )
          is the identity vector in C.  e_0 is an ml-vector of ones,
          e_k, k = 1,..., N, is the unit vector (1,0,...,0) of length
          mq[k], and e_k = vec(I) where I is the identity matrix of order
          ms[k].
        - 'dual slack': the smallest dual slack, sup {t | z >= t*e }.
        If the exit status is 'optimal', then the primal and dual
        infeasibilities are guaranteed to be less than

        Termination with status 'unknown' indicates that the algorithm
        failed to find a solution that satisfies the specified tolerances.
        In some cases, the returned solution may be fairly accurate.  If
        the primal and dual infeasibilities, the gap, and the relative gap
        are small, then x, y, s, z are close to optimal.
    Advanced usage.
        Three mechanisms are provided to express problem structure.
        1.  The user can provide a customized routine for solving linear
        equations (`KKT systems')
            [ P   A'  G'    ] [ ux ]   [ bx ]
            [ A   0   0     ] [ uy ] = [ by ].
            [ G   0   -W'*W ] [ uz ]   [ bz ]
        W is a scaling matrix, a block diagonal mapping
           W*u = ( W0*u_0, ..., W_{N+M}*u_{N+M} )
        defined as follows.
        - For the 'l' block (W_0):
              W_0 = diag(d),
          with d a positive vector of length ml.
        - For the 'q' blocks (W_{k+1}, k = 0, ..., N-1):
              W_{k+1} = beta_k * ( 2 * v_k * v_k' - J )
          where beta_k is a positive scalar, v_k is a vector in R^mq[k]
          with v_k[0] > 0 and v_k'*J*v_k = 1, and J = [1, 0; 0, -I].
        - For the 's' blocks (W_{k+N}, k = 0, ..., M-1):
              W_k * u = vec(r_k' * mat(u) * r_k)
          where r_k is a nonsingular matrix of order ms[k], and mat(x) is
          the inverse of the vec operation.
        The optional argument kktsolver is a Python function that will be
        called as g = kktsolver(W).  W is a dictionary that contains
        the parameters of the scaling:
        - W['d'] is a positive 'd' matrix of size (ml,1).
        - W['di'] is a positive 'd' matrix with the elementwise inverse of
          W['d'].
        - W['beta'] is a list [ beta_0, ..., beta_{N-1} ]
        - W['v'] is a list [ v_0, ..., v_{N-1} ]
        - W['r'] is a list [ r_0, ..., r_{M-1} ]
        - W['rti'] is a list [ rti_0, ..., rti_{M-1} ], with rti_k the
          inverse of the transpose of r_k.
        The call g = kktsolver(W) should return a function g that solves
        the KKT system by g(x, y, z).  On entry, x, y, z contain the
        righthand side bx, by, bz.  On exit, they contain the solution,
        with uz scaled, the argument z contains W*uz.  In other words,
        on exit x, y, z are the solution of
            [ P   A'  G'*W^{-1} ] [ ux ]   [ bx ]
            [ A   0   0         ] [ uy ] = [ by ].
            [ G   0   -W'       ] [ uz ]   [ bz ]
        2.  The linear operators P*u, G*u and A*u can be specified
        by providing Python functions instead of matrices.  This can only
        be done in combination with 1. above, i.e., it requires the
        kktsolver argument.
        If P is a function, the call P(u, v, alpha, beta) should evaluate
        the matrix-vectors product
            v := alpha * P * u + beta * v.
        The arguments u and v are required.  The other arguments have
        default values alpha = 1.0, beta = 0.0.

        If G is a function, the call G(u, v, alpha, beta, trans) should
        evaluate the matrix-vector products
            v := alpha * G * u + beta * v  if trans is 'N'
            v := alpha * G' * u + beta * v  if trans is 'T'.
        The arguments u and v are required.  The other arguments have
        default values alpha = 1.0, beta = 0.0, trans = 'N'.
        If A is a function, the call A(u, v, alpha, beta, trans) should
        evaluate the matrix-vectors products
            v := alpha * A * u + beta * v if trans is 'N'
            v := alpha * A' * u + beta * v if trans is 'T'.
        The arguments u and v are required.  The other arguments
        have default values alpha = 1.0, beta = 0.0, trans = 'N'.
        If X is the vector space of primal variables x, then:
        If this option is used, the argument q must be in the same format
        as x, the argument P must be a Python function, the arguments A
        and G must be Python functions or None, and the argument
        kktsolver is required.
        If Y is the vector space of primal variables y:
        If this option is used, the argument b must be in the same format
        as y, the argument A must be a Python function or None, and the
        argument kktsolver is required.
    """
    from cvxopt import base, blas, misc
    from cvxopt.base import matrix, spmatrix
    dims = None
    kktsolver = 'chol2'

    # Argument error checking depends on level of customization.
    customkkt = not isinstance(kktsolver, str)
    matrixP = isinstance(P, (matrix, spmatrix))
    matrixG = isinstance(G, (matrix, spmatrix))
    matrixA = isinstance(A, (matrix, spmatrix))
    if (not matrixP or (not matrixG and G is not None) or
            (not matrixA and A is not None)) and not customkkt:
        raise ValueError("use of function valued P, G, A requires a "
                         "user-provided kktsolver")
    if False and (matrixA or not customkkt):
        raise ValueError("use of non vector type for y requires "
                         "function valued A and user-provided kktsolver")

    if (not isinstance(q, matrix) or q.typecode != 'd' or q.size[1] != 1):
        raise TypeError("'q' must be a 'd' matrix with one column")

    if matrixP:
        if P.typecode != 'd' or P.size != (q.size[0], q.size[0]):
            raise TypeError("'P' must be a 'd' matrix of size (%d, %d)"
                            % (q.size[0], q.size[0]))

        def fP(x, y, alpha=1.0, beta=0.0):
            base.symv(P, x, y, alpha=alpha, beta=beta)
    else:
        fP = P

    if h is None:
        h = matrix(0.0, (0, 1))
    if not isinstance(h, matrix) or h.typecode != 'd' or h.size[1] != 1:
        raise TypeError("'h' must be a 'd' matrix with one column")

    if not dims:
        dims = {'l': h.size[0], 'q': [], 's': []}
    if not isinstance(dims['l'], (int, long)) or dims['l'] < 0:
        raise TypeError("'dims['l']' must be a nonnegative integer")
    if [k for k in dims['q'] if not isinstance(k, (int, long)) or k < 1]:
        raise TypeError("'dims['q']' must be a list of positive integers")
    if [k for k in dims['s'] if not isinstance(k, (int, long)) or k < 0]:
        raise TypeError("'dims['s']' must be a list of nonnegative "
                        "integers")

    if dims['q'] or dims['s']:
        refinement = 1
    else:
        refinement = 0

    cdim = dims['l'] + sum(dims['q']) + sum([k ** 2 for k in dims['s']])
    if h.size[0] != cdim:
        raise TypeError("'h' must be a 'd' matrix of size (%d,1)" % cdim)

    # Data for kth 'q' constraint are found in rows indq[k]:indq[k+1] of G.
    indq = [dims['l']]
    for k in dims['q']:
        indq = indq + [indq[-1] + k]

    # Data for kth 's' constraint are found in rows inds[k]:inds[k+1] of G.
    inds = [indq[-1]]
    for k in dims['s']:
        inds = inds + [inds[-1] + k ** 2]

    if G is None:
        G = spmatrix([], [], [], (0, q.size[0]))
        matrixG = True
    if matrixG:
        if G.typecode != 'd' or G.size != (cdim, q.size[0]):
            raise TypeError("'G' must be a 'd' matrix of size (%d, %d)"
                            % (cdim, q.size[0]))

        def fG(x, y, trans='N', alpha=1.0, beta=0.0):
            misc.sgemv(G, x, y, dims, trans=trans, alpha=alpha,
                       beta=beta)
    else:
        fG = G

    if A is None:
        A = spmatrix([], [], [], (0, q.size[0]))
        matrixA = True
    if matrixA:
        if A.typecode != 'd' or A.size[1] != q.size[0]:
            raise TypeError("'A' must be a 'd' matrix with %d columns"
                            % q.size[0])

        def fA(x, y, trans='N', alpha=1.0, beta=0.0):
            base.gemv(A, x, y, trans=trans, alpha=alpha, beta=beta)
    else:
        fA = A
    if b is None:
        b = matrix(0.0, (0, 1))
    if not isinstance(b, matrix) or b.typecode != 'd' or b.size[1] != 1:
        raise TypeError("'b' must be a 'd' matrix with one column")
    if matrixA and b.size[0] != A.size[0]:
        raise TypeError("'b' must have length %d" % A.size[0])

    ws3, wz3 = matrix(0.0, (cdim, 1)), matrix(0.0, (cdim, 1))

    def res(ux, uy, uz, us, vx, vy, vz, vs, W, lmbda):

        # Evaluates residual in Newton equations:
        #
        #      [ vx ]    [ vx ]   [ 0     ]   [ P  A'  G' ]   [ ux        ]
        #      [ vy ] := [ vy ] - [ 0     ] - [ A  0   0  ] * [ uy        ]
        #      [ vz ]    [ vz ]   [ W'*us ]   [ G  0   0  ]   [ W^{-1}*uz ]
        #
        #      vs := vs - lmbda o (uz + us).

        # vx := vx - P*ux - A'*uy - G'*W^{-1}*uz
        fP(ux, vx, alpha=-1.0, beta=1.0)
        fA(uy, vx, alpha=-1.0, beta=1.0, trans='T')
        blas.copy(uz, wz3)
        misc.scale(wz3, W, inverse='I')
        fG(wz3, vx, alpha=-1.0, beta=1.0, trans='T')

        # vy := vy - A*ux
        fA(ux, vy, alpha=-1.0, beta=1.0)

        # vz := vz - G*ux - W'*us
        fG(ux, vz, alpha=-1.0, beta=1.0)
        blas.copy(us, ws3)
        misc.scale(ws3, W, trans='T')
        blas.axpy(ws3, vz, alpha=-1.0)

        # vs := vs - lmbda o (uz + us)
        blas.copy(us, ws3)
        blas.axpy(uz, ws3)
        misc.sprod(ws3, lmbda, dims, diag='D')
        blas.axpy(ws3, vs, alpha=-1.0)

    # kktsolver(W) returns a routine for solving
    #
    #     [ P   A'  G'*W^{-1} ] [ ux ]   [ bx ]
    #     [ A   0   0         ] [ uy ] = [ by ].
    #     [ G   0   -W'       ] [ uz ]   [ bz ]

    factor = kkt_chol2(G, dims, A)

    def kktsolver(W):
        return factor(W, P)

    resx0 = max(1.0, math.sqrt(np.dot(q.T, q)))
    resy0 = max(1.0, math.sqrt(np.dot(b.T, b)))
    resz0 = max(1.0, misc.snrm2(h, dims))

    if cdim == 0:
        return solve_only_equalities_qp(kktsolver, fP, fA, resx0, resy0, dims)

    x, y = matrix(q), matrix(b)
    s, z = matrix(0.0, (cdim, 1)), matrix(0.0, (cdim, 1))

    # Factor
    #
    #     [ P   A'  G' ]
    #     [ A   0   0  ].
    #     [ G   0  -I  ]

    W = {}
    W['d'] = matrix(1.0, (dims['l'], 1))
    W['di'] = matrix(1.0, (dims['l'], 1))
    W['v'] = [matrix(0.0, (m, 1)) for m in dims['q']]
    W['beta'] = len(dims['q']) * [1.0]
    for v in W['v']:
        v[0] = 1.0
    W['r'] = [matrix(0.0, (m, m)) for m in dims['s']]
    W['rti'] = [matrix(0.0, (m, m)) for m in dims['s']]
    for r in W['r']:
        r[::r.size[0] + 1] = 1.0
    for rti in W['rti']:
        rti[::rti.size[0] + 1] = 1.0
    try:
        f = kktsolver(W)
    except ArithmeticError:
        raise ValueError("Rank(A) < p or Rank([P; A; G]) < n")

    # Solve
    #
    #     [ P   A'  G' ]   [ x ]   [ -q ]
    #     [ A   0   0  ] * [ y ] = [  b ].
    #     [ G   0  -I  ]   [ z ]   [  h ]

    x = matrix(np.copy(q))
    x *= -1.0
    y = matrix(np.copy(b))
    z = matrix(np.copy(h))
    try:
        f(x, y, z)
    except ArithmeticError:
        raise ValueError("Rank(A) < p or Rank([P; G; A]) < n")
    s = matrix(np.copy(z))
    blas.scal(-1.0, s)

    nrms = misc.snrm2(s, dims)
    ts = misc.max_step(s, dims)
    if ts >= -1e-8 * max(nrms, 1.0):
        a = 1.0 + ts
        s[:dims['l']] += a
        s[indq[:-1]] += a
        ind = dims['l'] + sum(dims['q'])
        for m in dims['s']:
            s[ind: ind + m * m: m + 1] += a
            ind += m ** 2

    nrmz = misc.snrm2(z, dims)
    tz = misc.max_step(z, dims)
    if tz >= -1e-8 * max(nrmz, 1.0):
        a = 1.0 + tz
        z[:dims['l']] += a
        z[indq[:-1]] += a
        ind = dims['l'] + sum(dims['q'])
        for m in dims['s']:
            z[ind: ind + m * m: m + 1] += a
            ind += m ** 2

    rx, ry, rz = matrix(q), matrix(b), matrix(0.0, (cdim, 1))
    dx, dy = matrix(x), matrix(y)
    dz, ds = matrix(0.0, (cdim, 1)), matrix(0.0, (cdim, 1))
    lmbda = matrix(0.0, (dims['l'] + sum(dims['q']) + sum(dims['s']), 1))
    lmbdasq = matrix(0.0, (dims['l'] + sum(dims['q']) + sum(dims['s']), 1))
    sigs = matrix(0.0, (sum(dims['s']), 1))
    sigz = matrix(0.0, (sum(dims['s']), 1))

    if show_progress:
        print("% 10s% 12s% 10s% 8s% 7s" % ("pcost", "dcost", "gap", "pres",
                                           "dres"))

    gap = misc.sdot(s, z, dims)

    for iters in range(MAXITERS + 1):

        # f0 = (1/2)*x'*P*x + q'*x + r and  rx = P*x + q + A'*y + G'*z.
        rx = matrix(np.copy(q))
        fP(x, rx, beta=1.0)
        f0 = 0.5 * (np.dot(x.T, rx) + np.dot(x.T, q))
        fA(y, rx, beta=1.0, trans='T')
        fG(z, rx, beta=1.0, trans='T')
        resx = math.sqrt(np.dot(rx.T, rx))

        # ry = A*x - b
        ry = matrix(np.copy(b))
        fA(x, ry, alpha=1.0, beta=-1.0)
        resy = math.sqrt(np.dot(ry.T, ry))

        # rz = s + G*x - h
        rz = matrix(np.copy(s))
        blas.axpy(h, rz, alpha=-1.0)
        fG(x, rz, beta=1.0)
        resz = misc.snrm2(rz, dims)

        # Statistics for stopping criteria.

        # pcost = (1/2)*x'*P*x + q'*x
        # dcost = (1/2)*x'*P*x + q'*x + y'*(A*x-b) + z'*(G*x-h)
        #       = (1/2)*x'*P*x + q'*x + y'*(A*x-b) + z'*(G*x-h+s) - z'*s
        #       = (1/2)*x'*P*x + q'*x + y'*ry + z'*rz - gap
        pcost = f0
        dcost = f0 + np.dot(y.T, ry) + misc.sdot(z, rz, dims) - gap
        if pcost < 0.0:
            relgap = gap / -pcost
        elif dcost > 0.0:
            relgap = gap / dcost
        else:
            relgap = None
        pres = max(resy / resy0, resz / resz0)
        dres = resx / resx0

        if show_progress:
            print("%2d: % 8.4e % 8.4e % 4.0e% 7.0e% 7.0e"
                  % (iters, pcost, dcost, gap, pres, dres))

        if (pres <= FEASTOL and dres <= FEASTOL and (gap <= ABSTOL or
                                                     (relgap is not None and relgap <= RELTOL))) or \
                iters == MAXITERS:
            ind = dims['l'] + sum(dims['q'])
            for m in dims['s']:
                misc.symm(s, m, ind)
                misc.symm(z, m, ind)
                ind += m ** 2
            ts = misc.max_step(s, dims)
            tz = misc.max_step(z, dims)
            if iters == MAXITERS:
                if show_progress:
                    print("Terminated (maximum number of iterations "
                          "reached).")
                status = 'unknown'
            else:
                if show_progress:
                    print("Optimal solution found.")
                status = 'optimal'
            return {'x': x, 'y': y, 's': s, 'z': z, 'status': status,
                    'gap': gap, 'relative gap': relgap,
                    'primal objective': pcost, 'dual objective': dcost,
                    'primal infeasibility': pres,
                    'dual infeasibility': dres, 'primal slack': -ts,
                    'dual slack': -tz, 'iterations': iters}

        # Compute initial scaling W and scaled iterates:
        #
        #     W * z = W^{-T} * s = lambda.
        #
        # lmbdasq = lambda o lambda.

        if iters == 0:
            W = misc.compute_scaling(s, z, lmbda, dims)
        misc.ssqr(lmbdasq, lmbda, dims)

        # f3(x, y, z) solves
        #
        #    [ P   A'  G'    ] [ ux        ]   [ bx ]
        #    [ A   0   0     ] [ uy        ] = [ by ].
        #    [ G   0   -W'*W ] [ W^{-1}*uz ]   [ bz ]
        #
        # On entry, x, y, z containg bx, by, bz.
        # On exit, they contain ux, uy, uz.

        try:
            f3 = kktsolver(W)
        except ArithmeticError:
            if iters == 0:
                raise ValueError("Rank(A) < p or Rank([P; A; G]) < n")
            else:
                ind = dims['l'] + sum(dims['q'])
                for m in dims['s']:
                    misc.symm(s, m, ind)
                    misc.symm(z, m, ind)
                    ind += m ** 2
                ts = misc.max_step(s, dims)
                tz = misc.max_step(z, dims)
                if show_progress:
                    print("Terminated (singular KKT matrix).")
                return {'x': x, 'y': y, 's': s, 'z': z,
                        'status': 'unknown', 'gap': gap,
                        'relative gap': relgap, 'primal objective': pcost,
                        'dual objective': dcost, 'primal infeasibility': pres,
                        'dual infeasibility': dres, 'primal slack': -ts,
                        'dual slack': -tz, 'iterations': iters}

        # f4_no_ir(x, y, z, s) solves
        #
        #     [ 0     ]   [ P  A'  G' ]   [ ux        ]   [ bx ]
        #     [ 0     ] + [ A  0   0  ] * [ uy        ] = [ by ]
        #     [ W'*us ]   [ G  0   0  ]   [ W^{-1}*uz ]   [ bz ]
        #
        #     lmbda o (uz + us) = bs.
        #
        # On entry, x, y, z, s contain bx, by, bz, bs.
        # On exit, they contain ux, uy, uz, us.

        def f4_no_ir(x, y, z, s):

            # Solve
            #
            #     [ P A' G'   ] [ ux        ]    [ bx                    ]
            #     [ A 0  0    ] [ uy        ] =  [ by                    ]
            #     [ G 0 -W'*W ] [ W^{-1}*uz ]    [ bz - W'*(lmbda o\ bs) ]
            #
            #     us = lmbda o\ bs - uz.
            #
            # On entry, x, y, z, s  contains bx, by, bz, bs.
            # On exit they contain x, y, z, s.

            # s := lmbda o\ s
            #    = lmbda o\ bs
            misc.sinv(s, lmbda, dims)

            # z := z - W'*s
            #    = bz - W'*(lambda o\ bs)
            ws3 = matrix(np.copy(s))
            misc.scale(ws3, W, trans='T')
            blas.axpy(ws3, z, alpha=-1.0)

            # Solve for ux, uy, uz
            f3(x, y, z)

            # s := s - z
            #    = lambda o\ bs - uz.
            blas.axpy(z, s, alpha=-1.0)

        # f4(x, y, z, s) solves the same system as f4_no_ir, but applies
        # iterative refinement.

        if iters == 0:
            if refinement:
                wx, wy = matrix(q), matrix(b)
                wz, ws = matrix(0.0, (cdim, 1)), matrix(0.0, (cdim, 1))
            if refinement:
                wx2, wy2 = matrix(q), matrix(b)
                wz2, ws2 = matrix(0.0, (cdim, 1)), matrix(0.0, (cdim, 1))

        def f4(x, y, z, s):
            if refinement:
                wx = matrix(np.copy(x))
                wy = matrix(np.copy(y))
                wz = matrix(np.copy(z))
                ws = matrix(np.copy(s))
            f4_no_ir(x, y, z, s)
            for i in range(refinement):
                wx2 = matrix(np.copy(wx))
                wy2 = matrix(np.copy(wy))
                wz2 = matrix(np.copy(wz))
                ws2 = matrix(np.copy(ws))
                res(x, y, z, s, wx2, wy2, wz2, ws2, W, lmbda)
                f4_no_ir(wx2, wy2, wz2, ws2)
                y += wx2
                y += wy2
                blas.axpy(wz2, z)
                blas.axpy(ws2, s)

        mu = gap / (dims['l'] + len(dims['q']) + sum(dims['s']))
        sigma, eta = 0.0, 0.0

        for i in [0, 1]:

            # Solve
            #
            #     [ 0     ]   [ P  A' G' ]   [ dx        ]
            #     [ 0     ] + [ A  0  0  ] * [ dy        ] = -(1 - eta) * r
            #     [ W'*ds ]   [ G  0  0  ]   [ W^{-1}*dz ]
            #
            #     lmbda o (dz + ds) = -lmbda o lmbda + sigma*mu*e (i=0)
            #     lmbda o (dz + ds) = -lmbda o lmbda - dsa o dza
            #                         + sigma*mu*e (i=1) where dsa, dza
            #                         are the solution for i=0.

            # ds = -lmbdasq + sigma * mu * e  (if i is 0)
            #    = -lmbdasq - dsa o dza + sigma * mu * e  (if i is 1),
            #     where ds, dz are solution for i is 0.
            blas.scal(0.0, ds)
            if i == 1:
                blas.axpy(ws3, ds, alpha=-1.0)
            blas.axpy(lmbdasq, ds, n=dims['l'] + sum(dims['q']),
                      alpha=-1.0)
            ds[:dims['l']] += sigma * mu
            ind = dims['l']
            for m in dims['q']:
                ds[ind] += sigma * mu
                ind += m
            ind2 = ind
            for m in dims['s']:
                blas.axpy(lmbdasq, ds, n=m, offsetx=ind2, offsety=ind, incy=m + 1, alpha=-1.0)
                ds[ind: ind + m * m: m + 1] += sigma * mu
                ind += m * m
                ind2 += m

            # (dx, dy, dz) := -(1 - eta) * (rx, ry, rz)
            dx *= 0.0
            dx += (-1.0 + eta) * rx

            dy *= 0.0
            dy += (-1.0 + eta) * ry
            blas.scal(0.0, dz)
            blas.axpy(rz, dz, alpha=-1.0 + eta)

            try:
                f4(dx, dy, dz, ds)
            except ArithmeticError:
                if iters == 0:
                    raise ValueError("Rank(A) < p or Rank([P; A; G]) < n")
                else:
                    ind = dims['l'] + sum(dims['q'])
                    for m in dims['s']:
                        misc.symm(s, m, ind)
                        misc.symm(z, m, ind)
                        ind += m ** 2
                    ts = misc.max_step(s, dims)
                    tz = misc.max_step(z, dims)
                    if show_progress:
                        print("Terminated (singular KKT matrix).")
                    return {'x': x, 'y': y, 's': s, 'z': z,
                            'status': 'unknown', 'gap': gap,
                            'relative gap': relgap, 'primal objective': pcost,
                            'dual objective': dcost,
                            'primal infeasibility': pres,
                            'dual infeasibility': dres, 'primal slack': -ts,
                            'dual slack': -tz, 'iterations': iters}

            dsdz = misc.sdot(ds, dz, dims)

            # Save ds o dz for Mehrotra correction
            if i == 0:
                ws3 = matrix(np.copy(ds))
                misc.sprod(ws3, dz, dims)

            # Maximum steps to boundary.
            #
            # If i is 1, also compute eigenvalue decomposition of the
            # 's' blocks in ds,dz.  The eigenvectors Qs, Qz are stored in
            # dsk, dzk.  The eigenvalues are stored in sigs, sigz.

            misc.scale2(lmbda, ds, dims)
            misc.scale2(lmbda, dz, dims)
            if i == 0:
                ts = misc.max_step(ds, dims)
                tz = misc.max_step(dz, dims)
            else:
                ts = misc.max_step(ds, dims, sigma=sigs)
                tz = misc.max_step(dz, dims, sigma=sigz)
            t = max([0.0, ts, tz])
            if t == 0:
                step = 1.0
            else:
                if i == 0:
                    step = min(1.0, 1.0 / t)
                else:
                    step = min(1.0, STEP / t)
            if i == 0:
                sigma = min(1.0, max(0.0,
                                     1.0 - step + dsdz / gap * step ** 2)) ** EXPON
                eta = 0.0

        x += step * dx
        y += step * dy

        # We will now replace the 'l' and 'q' blocks of ds and dz with
        # the updated iterates in the current scaling.
        # We also replace the 's' blocks of ds and dz with the factors
        # Ls, Lz in a factorization Ls*Ls', Lz*Lz' of the updated variables
        # in the current scaling.

        # ds := e + step*ds for nonlinear, 'l' and 'q' blocks.
        # dz := e + step*dz for nonlinear, 'l' and 'q' blocks.
        blas.scal(step, ds, n=dims['l'] + sum(dims['q']))
        blas.scal(step, dz, n=dims['l'] + sum(dims['q']))
        ind = dims['l']
        ds[:ind] += 1.0
        dz[:ind] += 1.0
        for m in dims['q']:
            ds[ind] += 1.0
            dz[ind] += 1.0
            ind += m

        # ds := H(lambda)^{-1/2} * ds and dz := H(lambda)^{-1/2} * dz.
        #
        # This replaced the 'l' and 'q' components of ds and dz with the
        # updated iterates in the current scaling.
        # The 's' components of ds and dz are replaced with
        #
        #     diag(lmbda_k)^{1/2} * Qs * diag(lmbda_k)^{1/2}
        #     diag(lmbda_k)^{1/2} * Qz * diag(lmbda_k)^{1/2}
        #
        misc.scale2(lmbda, ds, dims, inverse='I')
        misc.scale2(lmbda, dz, dims, inverse='I')

        # sigs := ( e + step*sigs ) ./ lambda for 's' blocks.
        # sigz := ( e + step*sigz ) ./ lmabda for 's' blocks.
        blas.scal(step, sigs)
        blas.scal(step, sigz)
        sigs += 1.0
        sigz += 1.0
        blas.tbsv(lmbda, sigs, n=sum(dims['s']), k=0, ldA=1, offsetA=dims['l'] + sum(dims['q']))
        blas.tbsv(lmbda, sigz, n=sum(dims['s']), k=0, ldA=1, offsetA=dims['l'] + sum(dims['q']))

        # dsk := Ls = dsk * sqrt(sigs).
        # dzk := Lz = dzk * sqrt(sigz).
        ind2, ind3 = dims['l'] + sum(dims['q']), 0
        for k in range(len(dims['s'])):
            m = dims['s'][k]
            for i in range(m):
                blas.scal(math.sqrt(sigs[ind3 + i]), ds, offset=ind2 + m * i,
                          n=m)
                blas.scal(math.sqrt(sigz[ind3 + i]), dz, offset=ind2 + m * i,
                          n=m)
            ind2 += m * m
            ind3 += m

        # Update lambda and scaling.
        misc.update_scaling(W, lmbda, ds, dz)

        # Unscale s, z (unscaled variables are used only to compute
        # feasibility residuals).

        blas.copy(lmbda, s, n=dims['l'] + sum(dims['q']))
        ind = dims['l'] + sum(dims['q'])
        ind2 = ind
        for m in dims['s']:
            blas.scal(0.0, s, offset=ind2)
            blas.copy(lmbda, s, offsetx=ind, offsety=ind2, n=m,
                      incy=m + 1)
            ind += m
            ind2 += m * m
        misc.scale(s, W, trans='T')

        blas.copy(lmbda, z, n=dims['l'] + sum(dims['q']))
        ind = dims['l'] + sum(dims['q'])
        ind2 = ind
        for m in dims['s']:
            blas.scal(0.0, z, offset=ind2)
            blas.copy(lmbda, z, offsetx=ind, offsety=ind2, n=m,
                      incy=m + 1)
            ind += m
            ind2 += m * m
        misc.scale(z, W, inverse='I')

        gap = blas.dot(lmbda, lmbda)


if __name__ == '__main__':
    from cvxopt.base import matrix

    Q = 2 * matrix([[2, .5], [.5, 1]])
    p = matrix([1.0, 1.0])
    G = matrix([[-1.0, 0.0], [0.0, -1.0]])
    h = matrix([0.0, 0.0])
    A = matrix([1.0, 1.0], (1, 2))
    b = matrix(1.0)
    #  print("Q")
    #  print(Q)
    #  print("p")
    #  print(p)
    #  print("G")
    #  print(G)
    #  print("h")
    #  print(h)
    #  print("A")
    #  print(A)
    #  print("b")
    #  print(b)
    sol = qp(Q, p, G, h, A, b)
    print(sol['x'])

    assert sol['x'][0] - 0.25 < 0.01
    assert sol['x'][1] - 0.75 < 0.01

    P = matrix(np.diag([1.0, 0.0]))
    q = matrix(np.array([3.0, 4.0]))
    G = matrix(np.array([[-1.0, 0.0], [0, -1.0], [-1.0, -3.0], [2.0, 5.0], [3.0, 4.0]]))
    h = matrix(np.array([0.0, 0.0, -15.0, 100.0, 80.0]))

    sol = qp(P, q, G=G, h=h)
    print(sol)
    print(sol["x"])
    assert sol['x'][0] - 0.00 < 0.01
    assert sol['x'][1] - 5.00 < 0.01

    P = matrix(np.diag([1.0, 0.0]))
    q = matrix(np.array([3.0, 4.0]))
    A = matrix([1.0, 1.0], (1, 2))
    b = matrix(1.0)
    sol = qp(P, q, A=A, b=b)  # no need iterration?
    print(sol)
    print(sol["x"])
    assert sol['x'][0] - 1.00 < 0.01
    assert sol['x'][1] - 0.00 < 0.01
